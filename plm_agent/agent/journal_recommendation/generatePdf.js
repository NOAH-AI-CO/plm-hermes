// generatePdf.js
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer');
const handlebars = require('handlebars');

// 1. 读取数据
async function readData() {
    return new Promise((resolve, reject) => {
        let inputData = '';
        process.stdin.on('data', (chunk) => {
            inputData += chunk;
        });
        process.stdin.on('end', () => {
            if (inputData) {
                try {
                    resolve(JSON.parse(inputData));
                } catch (e) {
                    reject(new Error('Invalid JSON from stdin'));
                }
            } else {
                // 如果 stdin 为空，尝试读取 data.json
                try {
                    const data = JSON.parse(fs.readFileSync('./data.json', 'utf-8'));
                    resolve(data);
                } catch (e) {
                    reject(new Error('No data from stdin and data.json not found'));
                }
            }
        });
        // 设置超时，防止 stdin 悬挂（如果是手动运行没传数据）
        setTimeout(() => {
            if (!inputData) {
                try {
                    const data = JSON.parse(fs.readFileSync('./data.json', 'utf-8'));
                    resolve(data);
                } catch (e) {
                    // ignore
                }
            }
        }, 100);
    });
}

const outputPath = process.argv[2] || 'journal-report.pdf';

(async () => {
    try {
        // 调试：输出路径信息
        console.log(`输出路径: ${outputPath}`);
        console.log(`输出路径类型: ${path.isAbsolute(outputPath) ? '绝对路径' : '相对路径'}`);
        console.log(`当前工作目录: ${process.cwd()}`);
        console.log(`__dirname: ${__dirname}`);
        
        // 确保输出目录存在
        const outputDir = path.dirname(outputPath);
        if (outputDir && !fs.existsSync(outputDir)) {
            fs.mkdirSync(outputDir, { recursive: true });
            console.log(`创建输出目录: ${outputDir}`);
        }
        
        const data = await readData();
        
        // 调试：检查数据
        console.log(`接收到的数据类型: ${typeof data}`);
        console.log(`数据键: ${Object.keys(data).join(', ')}`);
        console.log(`top_journals数量: ${data.top_journals ? data.top_journals.length : 0}`);
        if (data.top_journals && data.top_journals.length > 0) {
            console.log(`第一个期刊: ${data.top_journals[0].journal_title || 'Unknown'}`);
        }

        const convertToStars = (value) => {
            if (!value || isNaN(value)) return '—';
            const count = Math.max(1, Math.round(value / 100 * 5));
            return '★'.repeat(count);
        };

        // 自动添加星级字段
        if (data.top_journals) {
            data.top_journals.forEach((j) => {
                j.academic_stars = convertToStars(j.academic_dimension);
                j.relevance_stars = convertToStars(j.relevance_dimension);
                j.publishability_stars = convertToStars(j.publishability_dimension);

                // 处理中科院分区大类/小类
                if (j.zky_quartile) {
                    if (j.zky_quartile.major && j.zky_quartile.major.length > 0) {
                        const major = j.zky_quartile.major[0];
                        j.cas_major = `${major.category} ${major.quartile}区`;
                        if (!j.cas) j.cas = `${major.quartile}区`;
                    }
                    if (j.zky_quartile.minor && j.zky_quartile.minor.length > 0) {
                        j.cas_minor = j.zky_quartile.minor.map(m => `${m.category} ${m.quartile}区`).join(', ');
                    }
                } else {
                    if (j.zky_quartile_major) j.cas_major = j.zky_quartile_major;
                    if (j.zky_quartile_minor) j.cas_minor = j.zky_quartile_minor;
                }

                // 处理JCR分区格式
                if (j.jif_quartile) {
                    if (j.wos_research_areas && Array.isArray(j.wos_research_areas) && j.wos_research_areas.length > 0) {
                        const areas = j.wos_research_areas.slice(0, 2); // 最多取前2个领域
                        j.jcr = areas.map(area => `${area}${j.jif_quartile}`).join(', ');
                    } else {
                        // 如果没有研究领域，直接使用分区
                        j.jcr = j.jif_quartile;
                    }
                } else if (j.jcr && j.jcr !== 'Q1' && j.jcr !== 'Q2' && j.jcr !== 'Q3' && j.jcr !== 'Q4') {
                    // 如果jcr是期刊缩写（如"BREAST CANCER RES"），保持原样或尝试格式化
                    if (j.jif_quartile) {
                        j.jcr = `${j.jcr} ${j.jif_quartile}`;
                    }
                }

                // 处理影响因子字段兼容性
                if (!j.impact_factor && j.latest_impact_factor) {
                    j.impact_factor = j.latest_impact_factor;
                }

                if (!j.journal_title && j.journal_name) j.journal_title = j.journal_name;
            });
        }

        // 2. 读取模板
        const templatePath = path.resolve(__dirname, './report.hbs');
        console.log(`模板文件路径: ${templatePath}`);
        console.log(`模板文件存在: ${fs.existsSync(templatePath)}`);
        
        if (!fs.existsSync(templatePath)) {
            throw new Error(`模板文件不存在: ${templatePath}`);
        }
        
        const templateHtml = fs.readFileSync(templatePath, 'utf8');
        console.log(`模板文件大小: ${templateHtml.length} 字符`);
        
        const template = handlebars.compile(templateHtml);
        const html = template(data);
        console.log(`生成的HTML大小: ${html.length} 字符`);

        const browser = await puppeteer.launch({
            headless: 'new',
            args: ['--no-sandbox', '--disable-setuid-sandbox']
        });

        const page = await browser.newPage();

        await page.setContent(html, {
            waitUntil: 'networkidle0'
        });

        // 检查页面内容
        const pageContent = await page.evaluate(() => {
            return {
                textLength: document.body.innerText.length,
                htmlLength: document.body.innerHTML.length,
                scrollHeight: document.body.scrollHeight
            };
        });
        console.log(`页面内容检查: 文本长度=${pageContent.textLength}, HTML长度=${pageContent.htmlLength}, 页面高度=${pageContent.scrollHeight}px`);

        // 生成PDF - 不指定path，直接获取buffer然后手动写入
        console.log(`开始生成PDF到: ${outputPath}`);
        try {
            // 确保输出目录存在
            const outputDir = path.dirname(outputPath);
            if (!fs.existsSync(outputDir)) {
                fs.mkdirSync(outputDir, { recursive: true });
                console.log(`创建输出目录: ${outputDir}`);
            }
            
            // 生成PDF buffer（不指定path参数，避免写入失败）
            const pdfBuffer = await page.pdf({
                format: 'A4',
                printBackground: true,
                margin: {
                    top: '20mm',
                    bottom: '20mm',
                    left: '18mm',
                    right: '18mm'
                }
            });
            
            console.log(`PDF buffer大小: ${pdfBuffer ? pdfBuffer.length : 0} bytes`);
            
            // 手动写入文件
            if (pdfBuffer && pdfBuffer.length > 0) {
                fs.writeFileSync(outputPath, pdfBuffer);
                console.log(`PDF文件已写入: ${outputPath}`);
            } else {
                throw new Error(`PDF buffer为空，无法写入文件`);
            }
            
            console.log(`PDF生成完成`);
        } catch (pdfError) {
            console.error(`PDF生成错误: ${pdfError.message}`);
            console.error(`错误堆栈: ${pdfError.stack}`);
            throw pdfError;
        }

        await browser.close();
        
        // 验证PDF文件
        if (fs.existsSync(outputPath)) {
            const stats = fs.statSync(outputPath);
            console.log(`PDF文件验证: ${outputPath}`);
            console.log(`PDF文件大小: ${stats.size} bytes`);
            if (stats.size === 0) {
                throw new Error(`PDF文件大小为0，生成失败`);
            }
            if (stats.size < 1000) {
                console.warn(`⚠️ 警告: PDF文件很小 (${stats.size} bytes)，可能内容为空`);
            }
        } else {
            throw new Error(`PDF文件不存在: ${outputPath}`);
        }
    } catch (error) {
        console.error('Error:', error.message);
        process.exit(1);
    }
})();